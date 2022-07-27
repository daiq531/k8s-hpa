
#include "fcgi_stdio.h"
#include <stdlib.h>
#include <stdio.h>
#include <time.h>
#include <pthread.h>
#include <unistd.h>
#include <string.h>

#define INTERVAL_SECS 1

/* Basic type for the double-link list.  */
typedef struct list_head
{
  struct list_head *next;
  struct list_head *prev;
} list_t;

/* Define a variable with the head and tail of the list.  */
#define LIST_HEAD(name) \
  list_t name = { &(name), &(name) }

/* Add new element at the head of the list.  */
static inline void
list_add (list_t *newp, list_t *head)
{
  newp->next = head->next;
  newp->prev = head;
  head->next->prev = newp;
  // atomic_write_barrier ();
  head->next = newp;
}

/* Remove element from list.  */
static inline void
list_del (list_t *elem)
{
  elem->next->prev = elem->prev;
  elem->prev->next = elem->next;
}

/* Get typed element from list at a given position.  */
#define list_entry(ptr, type, member) \
  ((type *) ((char *) (ptr) - (unsigned long) (&((type *) 0)->member)))

/* Iterate forward over the elements of the list.  */
#define list_for_each(pos, head) \
  for (pos = (head)->next; pos != (head); pos = pos->next)

typedef struct mem_node {
    struct list_head list;
    unsigned int mem_size;
    time_t time;
} mem_node_t;

LIST_HEAD(head);
pthread_mutex_t mtx = PTHREAD_MUTEX_INITIALIZER;
unsigned int mem_total = 0;

void allocate_mem(unsigned int size)
{
    char* addr = (char*)malloc(size);
    if (NULL == addr)
        return;

    memset(addr, 0, size);
    mem_node_t* node = (mem_node_t*)addr;
    node->mem_size = size;
    time(&node->time);

    pthread_mutex_lock(&mtx);
    list_add((list_t*)node, &head);
    mem_total += size;
    pthread_mutex_unlock(&mtx);
}

void free_mem()
{
    list_t* pos;
    time_t now;

    pthread_mutex_lock(&mtx);
    list_for_each(pos, &head)
    {
        mem_node_t* node = (mem_node_t*)pos;
        if(node->time + INTERVAL_SECS < time(&now))
        {
            list_del(pos);
            mem_total -= node->mem_size;
            free((char*)pos);
        }
        else
        {
            break;
        }
    }
    pthread_mutex_unlock(&mtx);
}

/*********************************************************************/
/*
typedef struct mem_node {
    struct mem_node* next;
    char* mem_addr;
    unsigned int mem_size;
    time_t time;
} mem_node_t;

pthread_mutex_t mtx = PTHREAD_MUTEX_INITIALIZER;
mem_node_t* head = NULL;
mem_node_t* tail = NULL;
unsigned int mem_total = 0;

void allocate_mem(unsigned int size)
{
    char* addr = (char*)malloc(size);
    if (NULL == addr)
        return;

    memset(addr, 0, size);
    mem_node_t* node = (mem_node_t*)addr;
    node->next = NULL;
    node->mem_addr = (char*)addr;
    node->mem_size = size;
    time(&node->time);

    pthread_mutex_lock(&mtx);
    if((NULL == head) && (NULL == tail))
    {
        head = node;
        tail = node;
    }
    else
    {
        // put the node on the tail
        tail->next = node;
        tail = node;
    }
    pthread_mutex_unlock(&mtx);

    mem_total += size;

    return;
}

void free_mem()
{
    time_t now;
    mem_node_t* tmp = head;

    pthread_mutex_lock(&mtx);
    while(NULL != head)
    {
        if(time(&now) > (head->time + INTERVAL_SECS))
        {
            tmp = head;
            head = head->next;
            mem_total -= tmp->mem_size;
            free(tmp);
        }
        else
        {
            break;
        }
        if (NULL == head)
        {
            tail = NULL;
        }
    }
    pthread_mutex_unlock(&mtx);

    printf("timestamp: %s: occupied mem: %u\n", ctime(&now), mem_total);
}
*/

void* periodic_free_mem(void* arg)
{
    while(1)
    {
        free_mem();
        sleep(INTERVAL_SECS);
    }    
}

/*
int main()
{
    allocate_mem(100);
    allocate_mem(100);

    sleep(2);
    free_mem();
    free_mem();
    free_mem();
}
*/

int main()
{

    pthread_t thread;

    int ret = pthread_create(&thread, NULL, &periodic_free_mem, NULL);
    if(0 != ret)
    {
        printf("pthread_create fail!");
        return 0;
    }
    printf("create periodic free mem thread success.");

    char resp_buf[2048] = {0};
    while(FCGI_Accept() >= 0)
    {
        // get size from query string
        char* query_str = getenv("QUERY_STRING");
        char* loc = strchr(query_str, '=');
        if (NULL == loc) {
            continue;
        }
        int size = atoi(loc + 1);
        if(0 == size) {
            continue;
        }
        
        // allocate mem
        allocate_mem(size);

        char* format =
            "{ \
                QUERY_STRING: %s, \
                mem_total: %u \
            }";

        sprintf(resp_buf, format, getenv("QUERY_STRING"), mem_total);
        printf("Content-type: application/json\r\n"
               "\r\n"
               "%s", resp_buf);
    }
/*
    char *Data = ""
        "{"
            "\"message\": \"Hello FastCGI web app\""
        "}";
    while(FCGI_Accept() >=0 )
        printf("Content-type: application/json\r\n"
               "\r\n"
               "%s", Data);
*/
    return 0;
}
